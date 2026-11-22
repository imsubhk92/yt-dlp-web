import { expect, test } from "@playwright/test";

test("theme persists across reloads without changing the download form", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  const root = page.locator("html");
  const theme = page.getByLabel("Color theme");
  await expect(root).toHaveAttribute("data-theme", "dark");
  await expect(theme).toHaveValue("system");
  await expect(root).toHaveCSS("background-color", "rgb(16, 21, 34)");
  const url = page.getByLabel("Video or playlist URL");
  await url.fill("https://example.com/video");
  await theme.selectOption("light");
  await expect(root).toHaveAttribute("data-theme", "light");
  await expect(url).toHaveValue("https://example.com/video");
  await page.reload();
  await expect(theme).toHaveValue("light");
  await expect(root).toHaveCSS("background-color", "rgb(247, 248, 251)");
  await theme.selectOption("dark");
  await page.reload();
  await expect(root).toHaveAttribute("data-theme", "dark");
  await expect(theme).toHaveValue("dark");
  await page.screenshot({
    path: `test-results/theme-dark-${test.info().project.name}.png`,
    fullPage: true,
  });
  await theme.selectOption("light");
  await page.screenshot({
    path: `test-results/theme-light-${test.info().project.name}.png`,
    fullPage: true,
  });
  if (test.info().project.name === "mobile")
    await page.setViewportSize({ width: 320, height: 740 });
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth >
        document.documentElement.clientWidth,
    ),
  ).toBe(false);
  expect(errors).toEqual([]);
});
