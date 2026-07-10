import { Field, SelectInput, TextInput } from "./Field";
import { useI18n } from "../i18n/I18nProvider";
import type { JsonObject, JsonValue } from "../lib/api";
import type { ConnectorConfigSchema, ConnectorSchemaProperty } from "../lib/domain";

interface SchemaFormProps {
  schema: ConnectorConfigSchema;
  value: JsonObject;
  onChange: (next: JsonObject) => void;
  /** 已配置的密文字段名: 渲染"已配置, 留空保持不变"占位而非空输入。 */
  configuredSecrets?: string[];
  disabled?: boolean;
}

/**
 * config_schema 驱动的通用表单(方案 §4.1): v1 支持 string / secret / boolean /
 * number / enum 五种字段, 是未来连接器的公共积木。文案(title/description)由
 * 后端 schema 下发, 组件只负责渲染与取值。
 */
export function SchemaForm({ schema, value, onChange, configuredSecrets = [], disabled = false }: SchemaFormProps) {
  const { t } = useI18n();
  const properties = schema.properties ?? {};
  const required = new Set(schema.required ?? []);

  const setField = (name: string, fieldValue: JsonValue) => {
    onChange({ ...value, [name]: fieldValue });
  };

  return (
    <div className="grid gap-4">
      {Object.entries(properties).map(([name, property]) => (
        <SchemaField
          key={name}
          name={name}
          property={property}
          required={required.has(name)}
          value={value[name]}
          secretConfigured={configuredSecrets.includes(name)}
          disabled={disabled}
          onChange={(fieldValue) => setField(name, fieldValue)}
          secretPlaceholder={t("schemaForm.secretConfiguredPlaceholder")}
        />
      ))}
    </div>
  );
}

function SchemaField({
  name,
  property,
  required,
  value,
  secretConfigured,
  disabled,
  onChange,
  secretPlaceholder,
}: {
  name: string;
  property: ConnectorSchemaProperty;
  required: boolean;
  value: JsonValue | undefined;
  secretConfigured: boolean;
  disabled: boolean;
  onChange: (next: JsonValue) => void;
  secretPlaceholder: string;
}) {
  const label = `${property.title ?? name}${required ? " *" : ""}`;
  const isSecret = property["x-secret"] === true;

  if (property.enum && property.enum.length > 0) {
    return (
      <Field label={label} hint={property.description}>
        <SelectInput
          value={String(value ?? property.default ?? "")}
          disabled={disabled}
          onChange={(event) => onChange(event.currentTarget.value)}
        >
          <option value="" />
          {property.enum.map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </SelectInput>
      </Field>
    );
  }
  if (property.type === "boolean") {
    const checked = typeof value === "boolean" ? value : property.default === true;
    return (
      <Field label={label} hint={property.description} as="group">
        <label className="inline-flex items-center gap-2 text-body text-ink">
          <input
            type="checkbox"
            checked={checked}
            disabled={disabled}
            onChange={(event) => onChange(event.currentTarget.checked)}
          />
          <span>{property.title ?? name}</span>
        </label>
      </Field>
    );
  }
  if (property.type === "number") {
    return (
      <Field label={label} hint={property.description}>
        <TextInput
          type="number"
          value={typeof value === "number" ? String(value) : ""}
          disabled={disabled}
          onChange={(event) => {
            const raw = event.currentTarget.value;
            onChange(raw === "" ? null : Number(raw));
          }}
        />
      </Field>
    );
  }
  return (
    <Field label={label} hint={property.description}>
      <TextInput
        type={isSecret ? "password" : "text"}
        autoComplete={isSecret ? "new-password" : "off"}
        spellCheck={false}
        className="font-mono"
        placeholder={isSecret && secretConfigured ? secretPlaceholder : undefined}
        value={typeof value === "string" ? value : ""}
        disabled={disabled}
        onChange={(event) => onChange(event.currentTarget.value)}
      />
    </Field>
  );
}
