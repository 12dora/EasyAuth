import { KeyRound, Plus } from "lucide-react";
import { useState } from "react";

import { Button } from "../../../../components/Button";
import { Field, TextInput } from "../../../../components/Field";

type CreateCredentialKind = "static-tokens" | "oauth-clients";

interface CreateCredentialFormProps {
  isCreating: boolean;
  onCreateCredential: (kind: CreateCredentialKind, name: string) => Promise<unknown>;
}

export function CreateCredentialForm({ isCreating, onCreateCredential }: CreateCredentialFormProps) {
  const [name, setName] = useState("");

  const createCredential = (kind: CreateCredentialKind) => {
    // 创建进行中禁止再次触发, 从根源杜绝重复提交覆盖首个一次性明文。
    if (isCreating) {
      return;
    }
    void onCreateCredential(kind, name)
      .then(() => setName(""))
      .catch(() => undefined);
  };

  return (
    <div className="grid items-end gap-4 md:grid-cols-[minmax(0,1fr)_auto_auto]">
      <Field label="凭据名称">
        <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} placeholder="主接入凭据" />
      </Field>
      <Button variant="primary" icon={<Plus size={16} />} loading={isCreating} disabled={!name || isCreating} onClick={() => createCredential("static-tokens")}>
        静态 token
      </Button>
      <Button icon={<KeyRound size={16} />} disabled={!name || isCreating} onClick={() => createCredential("oauth-clients")}>
        OAuth client
      </Button>
    </div>
  );
}
