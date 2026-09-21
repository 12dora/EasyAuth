import { Field, TextInput } from "../../../../../components/Field";

/** 设置弹窗里所有数值输入的统一外观: Field 负责 label/hint/error 与无障碍关联。 */
export function UsageNumberField({
  label,
  hint,
  error,
  value,
  placeholder,
  min,
  max,
  step,
  onChange,
}: {
  label: string;
  hint: string;
  error?: string;
  value: string;
  placeholder?: string;
  min: number;
  max: number;
  step?: number | "any";
  onChange: (value: string) => void;
}) {
  return (
    <Field label={label} hint={hint} error={error}>
      <TextInput
        type="number"
        inputMode="numeric"
        className="tabular-nums"
        value={value}
        placeholder={placeholder}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(event.currentTarget.value)}
      />
    </Field>
  );
}
