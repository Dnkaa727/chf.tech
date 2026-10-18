export type ParticipantKind = "candidate" | "ai" | "human";

export interface Participant {
	id: string;
	name: string;
	kind: ParticipantKind;
	roleLabel: string;
	cameraOn: boolean;
	micOn: boolean;
	speaking: boolean;
}

export interface ChatMessage {
	id: string;
	authorId: string;
	authorName: string;
	authorKind: ParticipantKind;
	text: string;
	sentAt: number;
}

/* TODO: Переписать это всё */
export type StageContent =
	| { type: "avatar" }
	| { type: "image"; src: string; alt?: string }
	| { type: "video"; stream: MediaStream }
	| { type: "visualizer"; level: number };

export type ConferenceStatus =
	| "idle"
	| "connecting"
	| "waiting"
	| "live"
	| "reconnecting"
	| "ended";

export interface ConferenceState {
	status: ConferenceStatus;
}

export interface ConferenceNotice {
	id: number;
	text: string;
}

export type DeviceState = "on" | "off" | "denied";

export interface MediaState {
	camera: DeviceState;
	mic: DeviceState;
}

export const SELF_ID = "me";
