import { Copy, Plus } from "lucide-react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test, vi } from "vitest";

import { Badge } from "./Badge";
import { Button } from "./Button";
import { CodeBlock } from "./CodeBlock";
import { Dialog } from "./Dialog";
import { Field, SelectInput, TextArea, TextInput } from "./Field";
import { SecretDialog } from "./SecretDialog";
import { StatusBanner } from "./StatusBanner";
import { Toast } from "./Toast";
import { EmptyState } from "./ui/EmptyState";
import { PageState } from "./ui/PageState";
import { PanelSurface } from "./ui/PanelSurface";

describe("Button", () => {
  test("默认使用 outline 视觉并保持 md 高度", () => {
    render(<Button>返回</Button>);

    const button = screen.getByRole("button", { name: "返回" });
    expect(button).not.toHaveClass("button", "button-secondary");
    expect(button).toHaveClass("h-9", "border", "bg-paper");
  });

  test("支持尺寸、图标、loading 禁用点击", async () => {
    const onClick = vi.fn();
    render(
      <Button size="sm" variant="primary" icon={<Plus aria-hidden size={16} />} loading onClick={onClick}>
        保存
      </Button>,
    );

    const button = screen.getByRole("button", { name: "保存" });
    expect(button).toBeDisabled();
    expect(button).toHaveClass("h-7");
    expect(button.querySelector('[data-slot="spinner"]')).toHaveClass("size-3");

    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("Badge", () => {
  test("使用新版 tone, 不输出旧 badge class", () => {
    render(<Badge tone="evergreen">启用</Badge>);

    const badge = screen.getByText("启用");
    expect(badge).not.toHaveClass("badge", "badge-success");
    expect(badge).toHaveClass("bg-evergreen/10", "text-evergreen");
  });
});

describe("Dialog", () => {
  test("渲染可关闭的 xl 弹窗结构且不依赖旧 dialog class", async () => {
    const onClose = vi.fn();
    render(
      <Dialog title="创建应用" size="xl" onClose={onClose} footer={<Button>取消</Button>}>
        <p>表单内容</p>
      </Dialog>,
    );

    const dialog = screen.getByRole("dialog", { name: "创建应用" });
    expect(dialog).toHaveClass("max-w-4xl");
    expect(dialog).not.toHaveClass("dialog");
    expect(screen.getByText("表单内容")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "关闭弹窗" }));
    expect(onClose).toHaveBeenCalledOnce();
  });
});

describe("Toast", () => {
  test("使用 evergreen 和 signal tone", () => {
    const { rerender } = render(<Toast message="保存成功" />);

    expect(screen.getByRole("status")).toHaveClass("border-evergreen/20", "text-evergreen");

    rerender(<Toast tone="signal" message="保存失败" />);
    expect(screen.getByRole("status")).toHaveClass("border-signal/20", "text-signal");
    expect(screen.getByRole("status")).not.toHaveClass("toast", "toast-danger");
  });
});

describe("Field", () => {
  test("统一 label、hint、error 与表单控件 class", () => {
    render(
      <Field label="应用名称" hint="展示给用户" error="必填">
        <TextInput />
      </Field>,
    );

    const input = screen.getByLabelText("应用名称");
    expect(input).not.toHaveClass("control");
    expect(input).toHaveClass("h-9", "border", "bg-paper");
    expect(screen.getByText("展示给用户")).toHaveClass("text-ink-faint");
    expect(screen.getByText("必填")).toHaveClass("text-signal");
  });

  test("保留 textarea 和 select 导出名", () => {
    render(
      <>
        <TextArea aria-label="说明" />
        <SelectInput aria-label="状态">
          <option>启用</option>
        </SelectInput>
      </>,
    );

    expect(screen.getByLabelText("说明")).toHaveClass("min-h-24");
    expect(screen.getByLabelText("状态")).toHaveClass("h-9");
  });
});

describe("StatusBanner", () => {
  test("复用新版 tone 体系", () => {
    render(<StatusBanner tone="amber" title="需关注" message="配置未完成" />);

    const banner = screen.getByText("需关注").closest("div")?.parentElement;
    expect(banner).toHaveClass("border-amber-ink/20", "bg-amber-ink/10");
    expect(banner).not.toHaveClass("status-banner", "status-warning");
  });
});

describe("CodeBlock", () => {
  test("直接使用 Tailwind class 并支持复制", async () => {
    const writeText = vi.fn();
    Object.assign(navigator, { clipboard: { writeText } });

    render(<CodeBlock language="json" code={'{"ok":true}'} />);

    expect(screen.getByText("json").parentElement?.parentElement).not.toHaveClass("code-block");
    await userEvent.click(screen.getByRole("button", { name: "复制" }));
    expect(writeText).toHaveBeenCalledWith('{"ok":true}');
  });
});

describe("SecretDialog", () => {
  test("组合新版组件且不输出旧 secret-warning class", () => {
    render(
      <SecretDialog title="凭据已创建" primaryLabel="client_secret" primaryValue="secret_once" onClose={vi.fn()} />,
    );

    expect(screen.getByText(/明文凭据仅本次展示/)).not.toHaveClass("secret-warning");
    expect(screen.getByRole("dialog", { name: "凭据已创建" })).toBeInTheDocument();
    expect(screen.getByText("secret_once")).toBeInTheDocument();
  });
});

describe("UI primitives", () => {
  test("PanelSurface、EmptyState、PageState 提供纯 Tailwind 表面", () => {
    render(
      <PanelSurface>
        <EmptyState icon={<Copy aria-hidden />} title="暂无数据" description="创建后会显示在这里" />
        <PageState tone="bond" title="加载中" description="正在读取配置" />
      </PanelSurface>,
    );

    expect(screen.getByText("暂无数据").parentElement?.parentElement).toHaveClass("rounded-lg");
    expect(screen.getByText("加载中").parentElement).toHaveClass("text-center");
    expect(screen.getByText("暂无数据").closest("section")).toHaveClass("border", "bg-paper");
  });
});
