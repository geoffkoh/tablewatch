import type { ReactElement } from "react";
import { NotFound } from "./pages/NotFound";
import { Overview } from "./pages/Overview";

/**
 * Routing without a router library: this increment has one page. Every other
 * path is a client route the server answers with index.html (W3), so it gets
 * "page not found" here.
 */
export function App({ path }: { path: string }): ReactElement {
  if (path === "/" || path === "/index.html") return <Overview />;
  return <NotFound path={path} />;
}
