import { useState } from "react";
import { currentTheme, toggleTheme, type Theme } from "../lib/theme";

export function ThemeToggle() {
  const [theme, setThemeState] = useState<Theme>(currentTheme());
  return (
    <button
      className="btn-ghost"
      title="Theme wechseln"
      onClick={() => setThemeState(toggleTheme())}
    >
      {theme === "dark" ? "🌙" : "☀️"}
      <span className="hidden sm:inline">
        {theme === "dark" ? "Dunkel" : "Hell"}
      </span>
    </button>
  );
}
