"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { AppChrome } from "./AppChrome";

export function AuthShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [authorised, setAuthorised] = useState(pathname === "/login");

  useEffect(() => {
    if (pathname === "/login") {
      setAuthorised(true);
      return;
    }

    if (!window.localStorage.getItem("bidsense_token")) {
      setAuthorised(false);
      router.replace("/login");
      return;
    }

    setAuthorised(true);
  }, [pathname, router]);

  if (pathname === "/login") return children;
  if (!authorised) return null;
  return <AppChrome>{children}</AppChrome>;
}
