import { Dices } from "lucide-react";
import type { ChangeEvent } from "react";

import { useI18n } from "../i18n/I18nProvider";
import { Button } from "./Button";
import { TextInput } from "./Field";

interface AppKeyInputProps {
  id?: string;
  value: string;
  onChange: (value: string) => void;
  onGenerate: () => void;
  required?: boolean;
  "aria-describedby"?: string;
}

/** app_key 输入行: 文本框 + 自动生成按钮; 转发 id 保持 Field 的 label 关联。 */
export function AppKeyInput({ id, value, onChange, onGenerate, required, ...aria }: AppKeyInputProps) {
  const { t } = useI18n();

  return (
    <div className="flex items-center gap-2">
      <TextInput
        id={id}
        value={value}
        onChange={(event: ChangeEvent<HTMLInputElement>) => onChange(event.currentTarget.value)}
        required={required}
        {...aria}
      />
      <Button type="button" icon={<Dices size={15} />} onClick={onGenerate}>
        {t("appList.generateAppKey")}
      </Button>
    </div>
  );
}
