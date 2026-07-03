/** 生成符合 ^[a-z0-9][a-z0-9_-]{1,63}$ 的 app_key; 优先取名称中的 ASCII 片段, 否则用随机后缀。 */
export function generateAppKey(name: string): string {
  const slug = name
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^[-]+|[-]+$/g, "")
    .replace(/^[^a-z0-9]+/, "")
    .slice(0, 24)
    .replace(/[-]+$/g, "");
  const suffix = Math.random().toString(36).slice(2, 6);
  return slug ? `${slug}-${suffix}` : `app-${suffix}`;
}
