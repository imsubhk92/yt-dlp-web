import { expect, test } from "@playwright/test";

test("selects playlist entries, downloads a file and ZIP, and preserves history", async ({
  page,
}) => {
  const browserErrors: string[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/");
  await page
    .getByLabel("Video or playlist URL")
    .fill("https://example.com/list");
  await page.getByLabel("Include playlist").check();
  await page.getByRole("button", { name: "Find media" }).click();
  const preview = page.getByTestId("media-preview");
  await expect(preview.getByText("Weekend favorites")).toBeVisible();
  await preview.getByLabel("Select A removed video").uncheck();
  await expect(
    preview.getByLabel("Select Private", { exact: true }),
  ).toBeDisabled();
  await page.getByRole("button", { name: "Download 2 items" }).click();
  const card = page.locator(".job-card").first();
  await expect(card.locator(".status")).toHaveText("Completed");
  await expect(card.getByRole("link", { name: "Download ZIP" })).toBeVisible();
  const downloadEvent = page.waitForEvent("download");
  await card
    .getByRole("link", { name: "Save A quiet morning" })
    .first()
    .click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("same-title.mp4");
  const zipEvent = page.waitForEvent("download");
  await card.getByRole("link", { name: "Download ZIP" }).click();
  expect((await zipEvent).suggestedFilename()).toMatch(/playlist-.*\.zip/);
  await page.reload();
  await expect(page.locator(".job-card").first()).toContainText(
    "Weekend favorites",
  );
  await expect(page.locator(".job-card").first().locator(".status")).toHaveText(
    "Completed",
  );
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth >
      document.documentElement.clientWidth,
  );
  expect(overflow).toBe(false);
  expect(browserErrors).toEqual([]);
  await page.screenshot({
    path: `test-results/downstream-${test.info().project.name}.png`,
    fullPage: true,
  });
});
