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
    <div className="inline-form">
      <Field label="凭据名称">
        <TextInput value={name} onChange={(event) => setName(event.currentTarget.value)} placeholder="integration primary" />
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
