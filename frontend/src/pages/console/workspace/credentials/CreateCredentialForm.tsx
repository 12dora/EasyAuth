import { KeyRound, Plus } from "lucide-react";
import { useState } from "react";

import { Button } from "../../../../components/Button";
import { Field, TextInput } from "../../../../components/Field";

type CreateCredentialKind = "static-tokens" | "oauth-clients";

interface CreateCredentialFormProps {
  onCreateCredential: (kind: CreateCredentialKind, name: string) => Promise<unknown>;
}

export function CreateCredentialForm({ onCreateCredential }: CreateCredentialFormProps) {
  const [name, setName] = useState("");

  const createCredential = (kind: CreateCredentialKind) => {
    void onCreateCredential(kind, name)
      .then(() => setName(""))
      .catch(() => undefined);
  };

  return (
    <div className="grid items-end gap-4 rounded-lg border border-[rgb(var(--hairline-strong))] bg-paper p-5 shadow-sm md:grid-cols-[minmax(0,1fr)_auto_auto]">
      <Field label="凭据名称">
        <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} placeholder="主接入凭据" />
      </Field>
      <Button variant="primary" icon={<Plus size={16} />} disabled={!name} onClick={() => createCredential("static-tokens")}>
        静态 token
      </Button>
      <Button icon={<KeyRound size={16} />} disabled={!name} onClick={() => createCredential("oauth-clients")}>
        OAuth client
      </Button>
    </div>
  );
}
