"use client";

import { useEffect, useState } from "react";
import { Icon } from "@/components/ui/icon";
import { Wordmark } from "@/components/ui/mark";

const SECTIONS = [
  { href: "#loop", label: "The loop" },
  { href: "#guardrails", label: "Guardrails" },
  { href: "#proof", label: "Proof" },
  { href: "#build", label: "How it is built" },
];

export function SiteNav() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 24);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <header className="nav" data-scrolled={scrolled} data-open={open}>
      <div className="nav-bar shell">
        <Wordmark />

        <nav className="nav-links" aria-label="Sections">
          {SECTIONS.map((section) => (
            <a key={section.href} href={section.href}>
              {section.label}
            </a>
          ))}
        </nav>

        <div className="nav-actions">
          <a className="btn" data-variant="ghost" data-size="sm" href="/onboarding">
            Set up
          </a>
          <a className="btn" data-variant="solid" data-size="sm" href="/desk">
            Open the desk
            <Icon name="arrow" width={14} height={14} />
          </a>
        </div>

        <button
          className="icon-btn nav-toggle"
          type="button"
          aria-expanded={open}
          aria-controls="nav-panel"
          aria-label={open ? "Close menu" : "Open menu"}
          onClick={() => setOpen((value) => !value)}
        >
          <Icon name={open ? "close" : "menu"} />
        </button>
      </div>

      <div className="nav-panel" id="nav-panel" hidden={!open}>
        <div className="shell">
          {SECTIONS.map((section) => (
            <a key={section.href} href={section.href} onClick={() => setOpen(false)}>
              {section.label}
              <Icon name="arrow" width={15} height={15} />
            </a>
          ))}
          <a href="/onboarding" onClick={() => setOpen(false)}>
            Set up
            <Icon name="arrow" width={15} height={15} />
          </a>
          <a href="/desk" onClick={() => setOpen(false)}>
            Open the recovery desk
            <Icon name="arrow" width={15} height={15} />
          </a>
        </div>
      </div>
    </header>
  );
}
