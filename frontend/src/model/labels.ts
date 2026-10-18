import type { ParticipantKind } from "./types";

export const kindLabel: Record<ParticipantKind, string> = {
	candidate: "Кандидат",
	ai: "ИИ",
	human: "Человек",
};
