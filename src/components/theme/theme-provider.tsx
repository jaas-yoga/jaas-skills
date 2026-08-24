"use client";

import { ThemeProvider as NextThemesProvider } from "next-themes";
import type { ComponentProps } from "react";

/** The 4 built-in themes (ui-design.md §8.5.1). "system" is a picker option,
 * not a theme file — next-themes resolves it to "light" or "dark" itself. */
export const THEMES = ["light", "dark", "ocean", "violet"] as const;
export type ThemeName = (typeof THEMES)[number];

export function ThemeProvider({
  children,
  ...props
}: ComponentProps<typeof NextThemesProvider>) {
  return (
    <NextThemesProvider
      attribute="data-theme"
      themes={[...THEMES]}
      defaultTheme="system"
      enableSystem
      disableTransitionOnChange
      {...props}
    >
      {children}
    </NextThemesProvider>
  );
}
