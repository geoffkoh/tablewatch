import type { ReactElement } from "react";
import { parseRoute } from "./lib/route";
import { CheckPage } from "./pages/CheckPage";
import { Explorer } from "./pages/Explorer";
import { NotFound } from "./pages/NotFound";
import { Overview } from "./pages/Overview";

/**
 * Routing without a router library (spec 004, decision 7): `lib/route.ts`
 * parses the path, and links are plain `<a href>` with full page loads. Every
 * client path is answered with index.html by the server (spec 003, W3).
 */
export function App({ path, search = "" }: { path: string; search?: string }): ReactElement {
  const route = parseRoute(path);
  switch (route.page) {
    case "overview":
      return <Overview />;
    case "explorer":
      return <Explorer path={path} search={search} />;
    case "check":
      return <CheckPage id={route.id} />;
    case "not-found":
      return <NotFound path={path} />;
  }
}
