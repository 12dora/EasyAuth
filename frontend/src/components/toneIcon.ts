import { AlertCircle, CheckCircle2, Info, XCircle } from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { BadgeTone } from "../lib/status";

export function toneIcon(tone: BadgeTone): LucideIcon {
  switch (tone) {
    case "evergreen":
      return CheckCircle2;
    case "signal":
      return XCircle;
    case "amber":
      return AlertCircle;
    default:
      return Info;
  }
}
