import { ArrowRight } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Logo } from "@/components/Logo";

export function Footer() {
  return (
    <footer className="border-t border-border bg-card">
      <div className="mx-auto flex max-w-6xl flex-col gap-7 px-6 py-10 sm:flex-row sm:items-center sm:justify-between lg:px-8">
        <div className="flex items-center gap-3">
          <Logo />
          <span className="text-base font-semibold tracking-[0.14em] text-foreground">NXLYR</span>
          <p className="text-base text-muted-foreground">AI voice agents for considered property sales.</p>
        </div>
        <Button
          className="h-11 w-fit border-primary bg-primary px-5 text-primary-foreground shadow-md shadow-primary/20 hover:bg-primary/90"
          render={<a href="#demo" />}
          nativeButton={false}
        >
          Request a guided walkthrough <ArrowRight className="size-3.5" />
        </Button>
      </div>
    </footer>
  );
}
