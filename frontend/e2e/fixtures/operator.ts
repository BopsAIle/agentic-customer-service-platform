import { test as base } from "@playwright/test";

export const test = base.extend({
  page: async ({ page }, use) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await use(page);
  },
});

export { expect } from "@playwright/test";
