import { useState, useEffect, useCallback } from "react";
import { useAuth } from "./useAuth";
import { getUsage, ApiError } from "@/lib/api";

interface UserRoleState {
  role: "super_admin" | "admin" | "user" | null;
  isAdmin: boolean;
  isSuperAdmin: boolean;
  isLoading: boolean;
  remainingQueries: number;
  dailyLimit: number;
  chatRestricted: boolean;
}

interface UsageCheckResult {
  allowed: boolean;
  count: number;
  limit: number;
}

export function useUserRole() {
  const { user, isLoading: authLoading, isAuthenticated } = useAuth();
  const [state, setState] = useState<UserRoleState>({
    role: null,
    isAdmin: false,
    isSuperAdmin: false,
    isLoading: true,
    remainingQueries: 20,
    dailyLimit: 20,
    chatRestricted: false,
  });

  const fetchRole = useCallback(async () => {
    // Wait for auth to finish loading first
    if (authLoading) {
      return;
    }

    if (!isAuthenticated || !user) {
      setState({
        role: null,
        isAdmin: false,
        isSuperAdmin: false,
        isLoading: false,
        remainingQueries: 0,
        dailyLimit: 20,
        chatRestricted: false,
      });
      return;
    }

    try {
      // Role is now included in user data from JWT
      const role = (user.role as "super_admin" | "admin" | "user") || "user";

      // Fetch remaining queries
      const usage = await getUsage();

      setState({
        role,
        isAdmin: usage.is_admin,
        isSuperAdmin: usage.is_super_admin,
        isLoading: false,
        remainingQueries: usage.remaining === -1 ? Infinity : usage.remaining,
        dailyLimit: usage.limit === -1 ? Infinity : usage.limit,
        chatRestricted: usage.chat_restricted,
      });
    } catch (error) {
      console.error("Error fetching user role:", error);
      setState({
        role: "user",
        isAdmin: false,
        isSuperAdmin: false,
        isLoading: false,
        remainingQueries: 20,
        dailyLimit: 20,
        chatRestricted: false,
      });
    }
  }, [user, authLoading, isAuthenticated]);

  useEffect(() => {
    fetchRole();
  }, [fetchRole]);

  const checkAndIncrementUsage = useCallback(async (): Promise<UsageCheckResult> => {
    if (!isAuthenticated) {
      return { allowed: false, count: 0, limit: 20 };
    }

    if (state.isAdmin) {
      return { allowed: true, count: 0, limit: -1 };
    }

    // Usage is checked and incremented server-side during chat-sql call
    // This is just a pre-check based on current state
    if (state.remainingQueries <= 0) {
      return { allowed: false, count: state.dailyLimit, limit: state.dailyLimit };
    }

    // Optimistically decrement remaining queries
    setState(prev => ({
      ...prev,
      remainingQueries: Math.max(0, prev.remainingQueries - 1),
    }));

    return { 
      allowed: true, 
      count: state.dailyLimit - state.remainingQueries + 1, 
      limit: state.dailyLimit 
    };
  }, [isAuthenticated, state.isAdmin, state.remainingQueries, state.dailyLimit]);

  const refreshUsage = useCallback(async () => {
    if (!isAuthenticated) return;

    try {
      const usage = await getUsage();
      
      setState(prev => ({
        ...prev,
        remainingQueries: usage.remaining === -1 ? Infinity : usage.remaining,
        dailyLimit: usage.limit === -1 ? Infinity : usage.limit,
        isAdmin: usage.is_admin,
        isSuperAdmin: usage.is_super_admin,
      }));
    } catch (error) {
      console.error("Error refreshing usage:", error);
    }
  }, [isAuthenticated]);

  return {
    ...state,
    checkAndIncrementUsage,
    refreshUsage,
  };
}
