"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";
import { ArrowUpRight } from "lucide-react";

import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/button";

const navigation = [
  { href: "#features", label: "Features" },
  { href: "#what-we-do", label: "What we do" },
  { href: "#pipeline", label: "Pipeline" },
  { href: "#waitlist", label: "Get in Touch" },
];

export function Header() {
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    function updateVisibility() {
      const hero = document.getElementById("hero");
      const threshold = hero ? hero.offsetHeight * 0.8 : window.innerHeight * 0.8;
      setIsVisible(window.scrollY > threshold);
    }

    updateVisibility();
    window.addEventListener("scroll", updateVisibility, { passive: true });
    window.addEventListener("resize", updateVisibility);

    return () => {
      window.removeEventListener("scroll", updateVisibility);
      window.removeEventListener("resize", updateVisibility);
    };
  }, []);

  if (!isVisible) return null;

  return (
    <motion.header
      initial={{ opacity: 0, y: -12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.24, ease: "easeOut" }}
      className="fixed inset-x-0 top-0 z-50 border-b border-border/80 bg-background/92 backdrop-blur-md"
    >
      <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-6 lg:px-8">
        <a className="flex items-center gap-2.5" href="#hero" aria-label="NXLYR home">
          <Logo />
          <span className="text-base font-semibold tracking-[0.14em] text-foreground">NXLYR</span>
        </a>
        <nav className="hidden items-center gap-6 md:flex" aria-label="Primary navigation">
          {navigation.map((item) => (
            <a
              className="text-base text-foreground/65 transition-colors hover:text-foreground"
              href={item.href}
              key={item.href}
            >
              {item.label}
            </a>
          ))}
        </nav>
        <Button
          className="h-10 rounded-md bg-primary px-4 text-primary-foreground hover:bg-primary/90"
          render={<a href="#demo" />}
          nativeButton={false}
        >
          Try the live demo <ArrowUpRight className="size-3.5" />
        </Button>
      </div>
    </motion.header>
  );
}
