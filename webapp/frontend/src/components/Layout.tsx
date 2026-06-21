import type { ReactNode } from "react";

import NavBar from "./NavBar";

export interface LayoutProps {
  children: ReactNode;
}

/**
 * Page shell: a persistent NavBar on top, routed page content below.
 *
 * App.tsx renders `<Layout><Routes>…</Routes></Layout>`, so this component
 * takes `children` rather than react-router's <Outlet/>. Both patterns give
 * the same persistent-nav behaviour; we match the App contract exactly.
 */
export default function Layout({ children }: LayoutProps) {
  return (
    <div className="flex min-h-full flex-col bg-gray-50 text-gray-900">
      <NavBar />
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-2">
        {children}
      </main>
    </div>
  );
}
