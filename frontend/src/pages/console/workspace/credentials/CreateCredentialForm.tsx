import { KeyRound, Plus } from "lucide-react";
import { useState } from "react";

import { Button } from "../../../../components/Button";
import { Field, TextInput } from "../../../../components/Field";
import { useI18n } from "../../../../i18n/I18nProvider";
import type { AppCapabilityKey } from "../../../../lib/domain";

type CreateCredentialKind = "static-tokens" | "oauth-clients";

interface CreateCredentialFormProps {
  isCreating: boolean;
  onCreateCredential: (kind: CreateCredentialKind, name: string, capabilities: AppCapabilityKey[]) => Promise<unknown>;
}

export function CreateCredentialForm({ isCreating, onCreateCredential }: CreateCredentialFormProps) {
  const { t } = useI18n();
  const [name, setName] = useState("");
  const [capabilities, setCapabilities] = useState<AppCapabilityKey[]>([]);

  const createCredential = (kind: CreateCredentialKind) => {
    // 创建进行中禁止再次触发, 从根源杜绝重复提交覆盖首个一次性明文。
    if (isCreating) {
      return;
    }
    void onCreateCredential(kind, name, capabilities)
      .then(() => {
        setName("");
        setCapabilities([]);
      })
      .catch(() => undefined);
  };

  return (
    <div className="space-y-5">
      <Field label={t("wizard.credential.name")}>
        <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} placeholder={t("console.credentials.namePlaceholder")} />
      </Field>
      <Field as="group" label={t("console.credentials.capabilities")} hint={t("console.credentials.capabilitiesCreateHint")}>
        <div className="grid gap-2 sm:grid-cols-2">
          {(["directory", "notify"] as const).map((capability) => (
            <label key={capability} className="flex items-center gap-2 border border-ink/12 bg-paper-soft px-3 py-2 text-body text-ink">
              <input
                type="checkbox"
                checked={capabilities.includes(capability)}
                onChange={(event) => {
                  const checked = event.currentTarget.checked;
                  setCapabilities((current) => checked
                    ? [...current, capability]
                    : current.filter((item) => item !== capability));
                }}
              />
              <code>{capability}</code>
            </label>
          ))}
        </div>
      </Field>
      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="primary" icon={<Plus size={16} />} loading={isCreating} disabled={!name || isCreating} onClick={() => createCredential("static-tokens")}>
          {t("console.credentials.staticToken")}
        </Button>
        <Button icon={<KeyRound size={16} />} disabled={!name || isCreating} onClick={() => createCredential("oauth-clients")}>
          OAuth client
        </Button>
      </div>
    </div>
  );
}
