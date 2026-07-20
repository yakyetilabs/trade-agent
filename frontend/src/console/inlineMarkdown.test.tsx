import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderInlineMarkdown } from "./inlineMarkdown";

describe("renderInlineMarkdown", () => {
  it("wraps **text** in a <strong> and drops the asterisks", () => {
    const { container } = render(<p>{renderInlineMarkdown("A **held** shipment")}</p>);
    expect(container.querySelector("strong")).toHaveTextContent("held");
    expect(container).toHaveTextContent("A held shipment");
    expect(container.textContent).not.toContain("*");
  });

  it("wraps `code` in a <code> and drops the backticks", () => {
    const { container } = render(<p>{renderInlineMarkdown("run `classify` now")}</p>);
    expect(container.querySelector("code")).toHaveTextContent("classify");
    expect(container.textContent).not.toContain("`");
  });

  it("renders multiple spans and keeps the surrounding text", () => {
    const { container } = render(<p>{renderInlineMarkdown("**A** and **B** via `c`")}</p>);
    expect(container.querySelectorAll("strong")).toHaveLength(2);
    expect(container.querySelectorAll("code")).toHaveLength(1);
    expect(container).toHaveTextContent("A and B via c");
  });

  it("leaves an unclosed marker literal (a mid-stream typewriter reveal)", () => {
    const { container } = render(<p>{renderInlineMarkdown("**Investigating Held")}</p>);
    expect(container.querySelector("strong")).toBeNull();
    expect(container).toHaveTextContent("**Investigating Held");
  });

  it("returns plain text untouched", () => {
    const { container } = render(<p>{renderInlineMarkdown("just plain words")}</p>);
    expect(container.querySelector("strong")).toBeNull();
    expect(container.querySelector("code")).toBeNull();
    expect(container).toHaveTextContent("just plain words");
  });
});
