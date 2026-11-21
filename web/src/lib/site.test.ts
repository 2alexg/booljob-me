import { describe, expect, it } from "vitest";
import { site } from "./site";

describe("site", () => {
  it("is Hebrew-first and right-to-left", () => {
    expect(site.lang).toBe("he");
    expect(site.dir).toBe("rtl");
  });
});
