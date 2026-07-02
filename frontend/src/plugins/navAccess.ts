import type { NavItem, Role } from "./ViewRegistry";

/**
 * Filter plugin navigation items by current user role.
 *
 * Items declare their visibility via the `roles` field:
 *   - `roles` undefined → admin-only (default deny for users)
 *   - `roles: ["admin"]` → admins only
 *   - `roles: ["user"]`  → users only
 *   - `roles: ["admin", "user"]` → both
 *
 * `super_admin` is a superset of `admin`: it sees everything an admin sees.
 *
 * Returns an empty list when `role` is `null` (e.g. unauthenticated).
 */
export function filterNavItemsForRole(items: NavItem[], role: Role | null): NavItem[] {
  if (role === null) {
    return [];
  }
  return items.filter((item) => {
    if (!item.roles) {
      return role === "admin" || role === "super_admin";
    }
    if (role === "super_admin") {
      return item.roles.includes("super_admin") || item.roles.includes("admin");
    }
    return item.roles.includes(role);
  });
}
