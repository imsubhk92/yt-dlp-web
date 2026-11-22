// Apply before styles and React to avoid flashing the wrong background on reload.
(() => {
  let preference = "system";
  try {
    const saved = localStorage.getItem("downstream-theme");
    if (["system", "light", "dark"].includes(saved)) preference = saved;
  } catch {
    /* Storage is optional. */
  }
  const dark =
    preference === "dark" ||
    (preference === "system" &&
      window.matchMedia?.("(prefers-color-scheme: dark)")?.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  document.documentElement.style.colorScheme = dark ? "dark" : "light";
  document
    .querySelector('meta[name="theme-color"]')
    ?.setAttribute("content", dark ? "#101522" : "#f7f8fb");
})();
