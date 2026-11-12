import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";
import App from "./App";
import { bytes, duration } from "./api";

const preview = {
  id: "a".repeat(32),
  source_url: "https://example.com/list",
  title: "Weekend favorites",
  kind: "playlist",
  limit: 500,
  truncated: true,
  entries: [
    {
      id: "1",
      position: 1,
      title: "First video",
      url: "https://example.com/1",
      available: true,
      duration: 62,
      thumbnail: null,
    },
    {
      id: "2",
      position: 2,
      title: "Second video",
      url: "https://example.com/2",
      available: true,
      duration: null,
      thumbnail: null,
    },
    {
      id: "3",
      position: 3,
      title: "Private video",
      url: null,
      available: false,
      duration: null,
      thumbnail: null,
    },
  ],
};

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, options?: RequestInit) => {
      if (input.includes("/health"))
        return {
          ok: true,
          json: async () => ({
            ready: true,
            issues: [],
            dependencies: {},
            cookie_configured: false,
          }),
        };
      if (input.includes("/inspect"))
        return { ok: true, json: async () => preview };
      if (input === "/api/jobs" && options?.method === "POST")
        return { ok: true, json: async () => ({ id: "job" }) };
      return { ok: true, json: async () => [] };
    }),
  );
});
afterEach(() => vi.unstubAllGlobals());

test("inspects a playlist, marks unavailable items, and submits selected entries", async () => {
  const user = userEvent.setup();
  render(<App />);
  await user.type(
    screen.getByLabelText("Video or playlist URL"),
    "https://example.com/list",
  );
  await user.click(await screen.findByRole("button", { name: "Find media" }));
  expect(await screen.findByText("Weekend favorites")).toBeInTheDocument();
  expect(screen.getByLabelText("Select Private video")).toBeDisabled();
  expect(screen.getByText(/limited to the first 500/)).toBeInTheDocument();
  await user.click(screen.getByLabelText("Select Second video"));
  await user.click(screen.getByRole("button", { name: "Download video" }));
  await waitFor(() =>
    expect(fetch).toHaveBeenCalledWith(
      "/api/jobs",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({
          inspection_id: preview.id,
          entry_ids: ["1"],
          preset: "mp4",
          resolution: 1080,
        }),
      }),
    ),
  );
  expect(
    await screen.findByText(/Added to your downloads/),
  ).toBeInTheDocument();
});

test("changing the source invalidates the old preview", async () => {
  const user = userEvent.setup();
  render(<App />);
  const input = screen.getByLabelText("Video or playlist URL");
  await user.type(input, "https://example.com/list");
  await user.click(screen.getByRole("button", { name: "Find media" }));
  await screen.findByText("Weekend favorites");
  await user.type(input, "?changed=1");
  expect(screen.queryByTestId("media-preview")).not.toBeInTheDocument();
});

test("audio preset fixes the bitrate and select-all can clear selection", async () => {
  const user = userEvent.setup();
  render(<App />);
  await user.click(screen.getByRole("radio", { name: /MP3 audio/ }));
  expect(screen.getByLabelText("AUDIO QUALITY")).toBeDisabled();
  expect(screen.getByRole("option", { name: "192 kbps" })).toBeInTheDocument();
  await user.type(
    screen.getByLabelText("Video or playlist URL"),
    "https://example.com/list",
  );
  await user.click(screen.getByRole("button", { name: "Find media" }));
  await screen.findByText("Weekend favorites");
  await user.click(screen.getByLabelText("Select all available"));
  expect(screen.getByRole("button", { name: "Download audio" })).toBeDisabled();
});

test("API errors are visible and do not leave a preview", async () => {
  vi.mocked(fetch).mockImplementation(async (input) => {
    if (String(input).includes("/inspect"))
      return {
        ok: false,
        status: 422,
        json: async () => ({ detail: "This video is unavailable." }),
      } as Response;
    return {
      ok: true,
      json: async () =>
        String(input).includes("/health") ? { ready: true, issues: [] } : [],
    } as Response;
  });
  const user = userEvent.setup();
  render(<App />);
  await user.type(
    screen.getByLabelText("Video or playlist URL"),
    "https://example.com/video",
  );
  await user.click(screen.getByRole("button", { name: "Find media" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "This video is unavailable.",
  );
  expect(screen.queryByTestId("media-preview")).not.toBeInTheDocument();
});

test("formats unknown sizes, progress sizes, and durations truthfully", () => {
  expect(bytes(null)).toBe("Unknown size");
  expect(bytes(1024)).toBe("1.0 KB");
  expect(bytes(1024 ** 3)).toBe("1.00 GB");
  expect(duration(null)).toBe("—");
  expect(duration(3661)).toBe("1:01:01");
});
