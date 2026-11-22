import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import ThemeControl, { THEME_KEY } from "./ThemeControl";

let media: EventTarget & { matches: boolean };
beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  media = Object.assign(new EventTarget(), { matches: false });
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => media),
  );
});
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});
function systemDark(matches: boolean) {
  act(() => {
    media.matches = matches;
    media.dispatchEvent(new Event("change"));
  });
}
test("follows system appearance until an explicit theme is selected", async () => {
  const user = userEvent.setup();
  render(<ThemeControl />);
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
  systemDark(true);
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  await user.selectOptions(screen.getByLabelText("Color theme"), "light");
  systemDark(false);
  systemDark(true);
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
  expect(localStorage.getItem(THEME_KEY)).toBe("light");
  await user.selectOptions(screen.getByLabelText("Color theme"), "system");
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
});
test("restores a saved theme and ignores invalid saved values", () => {
  localStorage.setItem(THEME_KEY, "dark");
  const { unmount } = render(<ThemeControl />);
  expect(screen.getByLabelText("Color theme")).toHaveValue("dark");
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  unmount();
  localStorage.setItem(THEME_KEY, "invalid");
  render(<ThemeControl />);
  expect(screen.getByLabelText("Color theme")).toHaveValue("system");
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
});
test("switches appearance even if browser storage is blocked", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("Blocked");
  });
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("Blocked");
  });
  const user = userEvent.setup();
  render(<ThemeControl />);
  await user.selectOptions(screen.getByLabelText("Color theme"), "dark");
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
});
test("synchronizes a theme changed in another tab", () => {
  render(<ThemeControl />);
  act(() =>
    window.dispatchEvent(
      new StorageEvent("storage", { key: THEME_KEY, newValue: "dark" }),
    ),
  );
  expect(document.documentElement).toHaveAttribute("data-theme", "dark");
  act(() =>
    window.dispatchEvent(
      new StorageEvent("storage", { key: THEME_KEY, newValue: null }),
    ),
  );
  expect(document.documentElement).toHaveAttribute("data-theme", "light");
});
