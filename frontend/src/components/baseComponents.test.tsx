import { readFileSync } from "node:fs";
import { resolve } from "node:path";

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
import {
  TableBody,
  TableCell,
  TableFrame,
  TableHead,
  TableHeaderCell,
  TableRoot,
  TableRow,
  TableSkeletonRows,
} from "./ui/TablePrimitives";
import { TablePagination } from "./ui/TablePagination";
import { flexRender, getCoreRowModel, getPaginationRowModel, useReactTable, type ColumnDef } from "@tanstack/react-table";

const globalStylesCss = readFileSync(resolve(__dirname, "../styles/index.css"), "utf8");

describe("全局基础样式契约", () => {
  test("定义 paper-card 表面样式", () => {
    const paperCardRule = globalStylesCss.match(/\.paper-card\s*\{(?<body>[^}]*)\}/);

    expect(paperCardRule).not.toBeNull();
    expect(paperCardRule?.groups?.body).toMatch(/\bbackground\s*:/);
    expect(paperCardRule?.groups?.body).toMatch(/\bborder\s*:/);
    expect(paperCardRule?.groups?.body).toMatch(/\bbox-shadow\s*:/);
  });
});

describe("Button", () => {
  test("默认使用 outline 视觉并保持 md 高度", () => {
    render(<Button>返回</Button>);

    const button = screen.getByRole("button", { name: "返回" });
    expect(button).not.toHaveClass("button", "button-secondary");
    expect(button).toHaveClass("h-9", "border", "bg-transparent", "text-ink");
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
    expect(button).toHaveClass("h-7", "bg-ink", "text-paper");
    expect(button.querySelector('[data-slot="spinner"]')).toHaveClass("size-3");

    await userEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("Badge", () => {
  test("使用 EasyTrade badge 视觉 token", () => {
    render(<Badge tone="evergreen">启用</Badge>);

    const badge = screen.getByText("启用");
    expect(badge).not.toHaveClass("badge");
    expect(badge).toHaveClass("rounded-[2px]", "px-1.5", "py-0.5", "font-mono", "text-[10.5px]", "uppercase", "tracking-[0.14em]");
    expect(badge).toHaveClass("bg-[rgb(var(--evergreen))]/[0.08]", "text-[rgb(var(--evergreen))]");
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
    expect(dialog).toHaveClass("paper-card", "max-w-5xl", "rounded-[3px]", "p-0");
    expect(dialog).not.toHaveClass("dialog");
    expect(screen.getByText("表单内容")).toBeInTheDocument();

    const closeButton = screen.getByRole("button", { name: "关闭弹窗" });
    expect(closeButton).toHaveClass("border-transparent", "bg-transparent", "text-ink-soft");
    await userEvent.click(closeButton);
    expect(onClose).toHaveBeenCalledOnce();
  });

  test("支持 eyebrow、遮罩点击和 Escape 关闭", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <Dialog title="创建应用" eyebrow="Console" onClose={onClose}>
        <p>表单内容</p>
      </Dialog>,
    );

    expect(screen.getByText("Console")).toHaveClass("eyebrow");
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();

    await user.click(screen.getByRole("button", { name: "关闭弹窗遮罩" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });
});

describe("Toast", () => {
  test("使用 evergreen 和 signal tone", () => {
    const { rerender } = render(<Toast message="保存成功" />);

    expect(screen.getByRole("status")).toHaveClass("rounded-[2px]", "border-[rgb(var(--evergreen))]/30", "text-[rgb(var(--evergreen))]");

    rerender(<Toast tone="signal" message="保存失败" />);
    expect(screen.getByRole("status")).toHaveClass("border-[rgb(var(--signal))]/30", "text-[rgb(var(--signal))]");
    expect(screen.getByRole("status")).not.toHaveClass("toast");
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
    expect(screen.getByText("应用名称")).toHaveClass("text-[11px]", "uppercase", "tracking-[0.14em]", "text-ink-soft", "font-medium");
    expect(input).toHaveClass("h-9", "rounded-[2px]", "border-ink/15", "bg-paper-soft", "text-[13px]", "focus:border-[rgb(var(--amber))]");
    expect(input).not.toHaveClass("shadow-sm", "focus:ring-2");
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
    expect(banner).toHaveClass("border-[rgb(var(--amber))]/30", "bg-[rgb(var(--amber))]/[0.08]");
    expect(banner).not.toHaveClass("status-banner");
  });
});

describe("CodeBlock", () => {
  test("直接使用 Tailwind class 并支持复制", async () => {
    const writeText = vi.fn();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });

    render(<CodeBlock language="json" code={'{"ok":true}'} />);

    const codeBlock = screen.getByText("json").parentElement?.parentElement;
    expect(codeBlock).toHaveClass("rounded-[3px]", "border-[rgb(var(--hairline-strong))]", "bg-ink", "text-paper");
    expect(codeBlock).not.toHaveClass("code-block");
    await userEvent.click(screen.getByRole("button", { name: "复制" }));
    expect(writeText).toHaveBeenCalledWith('{"ok":true}');
  });
});

describe("SecretDialog", () => {
  test("组合新版组件并使用 amber token 警示块", () => {
    render(
      <SecretDialog title="凭据已创建" primaryLabel="client_secret" primaryValue="secret_once" onClose={vi.fn()} />,
    );

    expect(screen.getByText(/明文凭据仅本次展示/)).toHaveClass(
      "rounded-[3px]",
      "border-[rgb(var(--amber))]/30",
      "bg-[rgb(var(--amber))]/[0.08]",
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

    expect(screen.getByText("暂无数据").parentElement).toHaveClass("rounded-[3px]", "bg-paper-soft");
    expect(screen.getByText("加载中").parentElement).toHaveClass("rounded-[3px]", "bg-paper-soft", "text-center");
    expect(screen.getByText("暂无数据").closest("section")).toHaveClass("paper-card", "p-4");
  });

  test("TablePrimitives 使用 EasyTrade 表格视觉 token", () => {
    const { container } = render(
      <TableFrame data-testid="table-frame">
        <TableRoot>
          <TableHead>
            <TableRow>
              <TableHeaderCell>名称</TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            <TableRow>
              <TableCell>EasyAuth</TableCell>
            </TableRow>
            <TableSkeletonRows columns={1} rows={1} />
          </TableBody>
        </TableRoot>
      </TableFrame>,
    );

    const frame = screen.getByTestId("table-frame");
    expect(frame).toHaveClass("paper-card", "overflow-hidden", "rounded-[3px]", "p-0");
    expect(frame.firstElementChild).toHaveClass("overflow-x-auto");
    expect(container.querySelector("table")).toHaveClass("min-w-full", "border-separate", "border-spacing-0", "text-[13px]");
    expect(container.querySelector("thead")).toHaveClass("bg-paper-deep/60");
    expect(screen.getByRole("columnheader", { name: "名称" })).toHaveClass(
      "border-b",
      "border-ink/15",
      "px-3",
      "py-2.5",
      "text-left",
      "align-bottom",
      "font-mono",
      "text-[10.5px]",
      "uppercase",
      "tracking-[0.14em]",
      "text-ink-soft",
      "font-medium",
    );
    expect(screen.getByRole("cell", { name: "EasyAuth" })).toHaveClass(
      "border-b",
      "border-ink/8",
      "px-3",
      "py-2.5",
      "text-[13px]",
      "text-ink",
      "align-middle",
    );
    expect(container.querySelector("tr")).toHaveClass("hover:bg-[rgb(var(--amber))]/[0.05]");
    expect(container.querySelector(".animate-shimmer")).toHaveClass("bg-paper-deep");
  });

  test("TablePagination 支持翻页和切换每页条目数", async () => {
    const user = userEvent.setup();
    render(<PaginatedFixture />);

    expect(screen.getByText("第 1-10 条 / 共 12 条")).toBeInTheDocument();
    expect(screen.getByText("item-10")).toBeInTheDocument();
    expect(screen.queryByText("item-11")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "下一页" }));
    expect(await screen.findByText("第 11-12 条 / 共 12 条")).toBeInTheDocument();
    expect(screen.getByText("item-11")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "下一页" })).toBeDisabled();

    await user.selectOptions(screen.getByLabelText("每页条目数"), "5");
    expect(await screen.findByText("第 1-5 条 / 共 12 条")).toBeInTheDocument();
    expect(screen.getByText("item-5")).toBeInTheDocument();
    expect(screen.queryByText("item-6")).not.toBeInTheDocument();
  });
});

function PaginatedFixture() {
  const table = useReactTable({
    data: paginatedData,
    columns: paginatedColumns,
    getCoreRowModel: getCoreRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageIndex: 0, pageSize: 10 } },
  });

  return (
    <TableFrame>
      <TableRoot>
        <TableHead>
          {table.getHeaderGroups().map((headerGroup) => (
            <TableRow key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <TableHeaderCell key={header.id}>
                  {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                </TableHeaderCell>
              ))}
            </TableRow>
          ))}
        </TableHead>
        <TableBody>
          {table.getRowModel().rows.map((row) => (
            <TableRow key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <TableCell key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</TableCell>
              ))}
            </TableRow>
          ))}
        </TableBody>
      </TableRoot>
      <TablePagination table={table} />
    </TableFrame>
  );
}

type PaginatedRow = { name: string };

const paginatedData: PaginatedRow[] = Array.from({ length: 12 }, (_, index) => ({ name: `item-${index + 1}` }));
const paginatedColumns: ColumnDef<PaginatedRow>[] = [{ header: "名称", accessorKey: "name" }];
