export type PrimaryPage = "discover" | "subscriptions" | "workspace" | "cross-cloud" | "strm" | "media-server" | "system";

export type AppRoute = {
  page: PrimaryPage;
  section?: string;
};

const legacyRouteMap: Record<string, AppRoute> = {
  cloud: { page: "workspace" },
  tracking: { page: "subscriptions" },
  wishlist: { page: "subscriptions" },
  review: { page: "subscriptions", section: "review" },
  settings: { page: "system" },
  push: { page: "system", section: "notifications" },
  "settings-notifications": { page: "system", section: "notifications" },
  "settings-interaction": { page: "system", section: "notifications" },
  "settings-transfer-records": { page: "system", section: "notifications" },
  "settings-webhook": { page: "workspace", section: "webhook" },
  "settings-network": { page: "system", section: "network" },
  "settings-drives": { page: "workspace" },
  "settings-wishlist": { page: "subscriptions" },
  "settings-openlist": { page: "cross-cloud" },
};

export function routeFromHash(hash = window.location.hash): AppRoute {
  const value = hash.replace(/^#/, "").replace(/^\/+|\/+$/g, "");
  if (!value || value === "discover") return { page: "discover" };
  if (legacyRouteMap[value]) return legacyRouteMap[value];
  if (value === "system/openlist") return { page: "cross-cloud" };
  if (value === "system/webhook") return { page: "workspace", section: "webhook" };

  const [page, section] = value.split("/");
  if (page === "discover" || page === "workspace" || page === "subscriptions" || page === "cross-cloud" || page === "strm" || page === "media-server" || page === "system") {
    return { page, section: section || undefined };
  }
  return { page: "discover" };
}

export function hashForRoute(route: AppRoute): string {
  return `#${route.page}${route.section ? `/${route.section}` : ""}`;
}

export function sameRoute(left: AppRoute, right: AppRoute): boolean {
  return left.page === right.page && left.section === right.section;
}
