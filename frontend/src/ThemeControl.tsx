import { useEffect, useState } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

export const THEME_KEY = "downstream-theme";
type Preference = "system" | "light" | "dark";

function valid(value: unknown): value is Preference {
  return value === "system" || value === "light" || value === "dark";
}

function readPreference(): Preference {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (valid(saved)) return saved;
  } catch {
    // Storage can be blocked; the control still works for this session.
  }
  return "system";
}

function apply(preference: Preference) {
  const dark = window.matchMedia?.("(prefers-color-scheme: dark)")?.matches;
  const theme =
    preference === "system" ? (dark ? "dark" : "light") : preference;
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", theme === "dark" ? "#101522" : "#f7f8fb");
}

export default function ThemeControl() {
  const [preference, setPreference] = useState<Preference>(readPreference);
  useEffect(() => {
    apply(preference);
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    const changed = () => apply(preference);
    media?.addEventListener("change", changed);
    return () => media?.removeEventListener("change", changed);
  }, [preference]);
  useEffect(() => {
    const changed = (event: StorageEvent) => {
      if (event.key === THEME_KEY || event.key === null) {
        setPreference(valid(event.newValue) ? event.newValue : "system");
      }
    };
    window.addEventListener("storage", changed);
    return () => window.removeEventListener("storage", changed);
  }, []);
  const Icon =
    preference === "system" ? Monitor : preference === "dark" ? Moon : Sun;
  return (
    <label className="theme-control" title="Color theme">
      <span className="sr-only">Color theme</span>
      <Icon size={15} aria-hidden="true" />
      <select
        value={preference}
        onChange={(event) => {
          const next = event.target.value;
          if (!valid(next)) return;
          setPreference(next);
          try {
            localStorage.setItem(THEME_KEY, next);
          } catch {
            /* Persistence is optional. */
          }
        }}
      >
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </label>
  );
}
