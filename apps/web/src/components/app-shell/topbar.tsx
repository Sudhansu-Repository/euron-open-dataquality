"use client";

import { LogInIcon, MenuIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import * as React from "react";

import { BrandLogo } from "@/components/brand";
import { ThemeToggle } from "@/components/theme-toggle";
import { buttonVariants, Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { usePermissions } from "@/features/auth/api";
import { loginUrl } from "@/lib/auth-redirect";

import { SidebarNav } from "./sidebar";
import { UserMenu } from "./user-menu";

export function Topbar() {
  const [menuOpen, setMenuOpen] = React.useState(false);
  const { signedIn } = usePermissions();
  const pathname = usePathname();

  return (
    <header className="sticky top-0 z-30 bg-background/80 backdrop-blur-md supports-[backdrop-filter]:bg-background/70">
      <div className="flex h-14 items-center gap-2 px-4 sm:px-6 lg:px-8">
        <Button variant="subtle" size="icon" className="-ml-2 lg:hidden" aria-label="Open navigation" onClick={() => setMenuOpen(true)}>
          <MenuIcon />
        </Button>
        <Link href="/" className="rounded-lg lg:hidden" aria-label="DataQuality home">
          <BrandLogo />
        </Link>
        <div className="ml-auto flex items-center gap-1">
          <ThemeToggle />
          {signedIn ? (
            <UserMenu />
          ) : (
            <Link href={loginUrl(pathname)} className={buttonVariants({ size: "sm", className: "ml-1" })}>
              <LogInIcon />
              Sign in
            </Link>
          )}
        </div>
      </div>
      <Sheet open={menuOpen} onOpenChange={setMenuOpen}>
        <SheetContent side="left" className="bg-sidebar">
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <div className="flex h-14 items-center px-4">
            <BrandLogo />
          </div>
          <div className="overflow-y-auto px-3 pb-6">
            <SidebarNav onNavigate={() => setMenuOpen(false)} />
          </div>
        </SheetContent>
      </Sheet>
    </header>
  );
}
