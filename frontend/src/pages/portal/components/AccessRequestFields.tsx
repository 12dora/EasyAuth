import { Field, SelectInput, TextArea, TextInput } from "../../../components/Field";
import type { AccessGrantType } from "../hooks/useAccessRequestForm";

interface AccessRequestFieldsProps {
  grantType: AccessGrantType;
  expiresAt: string;
  reason: string;
  onGrantTypeChange: (grantType: AccessGrantType) => void;
  onExpiresAtChange: (expiresAt: string) => void;
  onReasonChange: (reason: string) => void;
}

export function AccessRequestFields({
  grantType,
  expiresAt,
  reason,
  onGrantTypeChange,
  onExpiresAtChange,
  onReasonChange,
}: AccessRequestFieldsProps) {
  return (
    <>
      <Field label="授权期限">
        <SelectInput value={grantType} onChange={(event) => onGrantTypeChange(event.currentTarget.value as AccessGrantType)}>
          <option value="permanent">长期</option>
          <option value="timed">限时</option>
        </SelectInput>
      </Field>
      {grantType === "timed" ? (
        <Field label="过期时间">
          <TextInput type="datetime-local" value={expiresAt} onChange={(event) => onExpiresAtChange(event.currentTarget.value)} />
        </Field>
      ) : null}
      <Field label="申请原因">
        <TextArea rows={4} value={reason} onChange={(event) => onReasonChange(event.currentTarget.value)} />
      </Field>
    </>
  );
}
