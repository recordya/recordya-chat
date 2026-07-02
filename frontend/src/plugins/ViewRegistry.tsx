import React, { ComponentType, Suspense, lazy } from "react";

export type Role = "super_admin" | "admin" | "user";

export interface ViewConfig {
  id: string;
  path: string;
  component: ComponentType<ViewProps>;
  pluginId: string;
  showInNav?: boolean;
  navLabel?: string;
  navIcon?: string;
  navOrder?: number;
  permissions?: string[];
  roles?: Role[];
}

export interface LazyViewConfig extends Omit<ViewConfig, "component"> {
  loader: () => Promise<{ default: ComponentType<ViewProps> }>;
}

export interface ViewProps {
  params?: Record<string, string>;
  query?: Record<string, string>;
}

export interface NavItem {
  id: string;
  path: string;
  label: string;
  icon?: string;
  order: number;
  pluginId: string;
  roles?: Role[];
}

interface RegisteredView {
  config: ViewConfig;
  lazyComponent: React.LazyExoticComponent<ComponentType<ViewProps>> | null;
}

function ViewLoading() {
  return (
    <div className="flex items-center justify-center h-full">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500"></div>
    </div>
  );
}

class ViewRegistry {
  private views = new Map<string, RegisteredView>();

  register(config: ViewConfig): void {
    this.views.set(config.id, {
      config,
      lazyComponent: null,
    });
  }

  registerLazy(config: LazyViewConfig): void {
    const lazyComponent = lazy(config.loader);
    const fullConfig: ViewConfig = {
      ...config,
      component: lazyComponent as unknown as ComponentType<ViewProps>,
    };
    this.views.set(config.id, {
      config: fullConfig,
      lazyComponent,
    });
  }

  unregister(id: string): void {
    this.views.delete(id);
  }

  unregisterPlugin(pluginId: string): void {
    for (const [id, view] of this.views.entries()) {
      if (view.config.pluginId === pluginId) {
        this.views.delete(id);
      }
    }
  }

  getRoutes(): { path: string; element: React.ReactElement }[] {
    return Array.from(this.views.values()).map((view) => {
      const Component = view.config.component;
      const element = view.lazyComponent ? (
        <Suspense fallback={<ViewLoading />}>
          <Component />
        </Suspense>
      ) : (
        <Component />
      );
      return { path: view.config.path, element };
    });
  }

  getNavItems(): NavItem[] {
    return Array.from(this.views.values())
      .filter((v) => v.config.showInNav)
      .map((v) => ({
        id: v.config.id,
        path: v.config.path,
        label: v.config.navLabel || v.config.id,
        icon: v.config.navIcon,
        order: v.config.navOrder ?? 100,
        pluginId: v.config.pluginId,
        roles: v.config.roles,
      }))
      .sort((a, b) => a.order - b.order);
  }

  /**
   * Get the rendered element for a view by its registry id.
   * Used by IconRail to render plugin views inline.
   */
  getViewElement(id: string): React.ReactElement | null {
    const view = this.views.get(id);
    if (!view) return null;
    const Component = view.config.component;
    if (view.lazyComponent) {
      return (
        <Suspense fallback={<ViewLoading />}>
          <Component />
        </Suspense>
      );
    }
    return <Component />;
  }
}

export const viewRegistry = new ViewRegistry();
export { ViewLoading };
