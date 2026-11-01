import type { Readable } from "./store";
import type {
	ChatMessage,
	ConferenceNotice,
	ConferenceState,
	MediaState,
	Participant,
	StageContent,
} from "../model/types";

export interface ConferenceService {
	state: Readable<ConferenceState>;
	events: Readable<ConferenceNotice | null>;
	join(name: string): Promise<void>;
	leave(): Promise<void>;
}

export interface ParticipantsService {
	list: Readable<Participant[]>;
	content: Readable<Record<string, StageContent>>;
}

export interface MediaService {
	devices: Readable<MediaState>;
	localStream: Readable<MediaStream>;
	setCamera(on: boolean): Promise<void>;
	setMic(on: boolean): Promise<void>;
}

export interface ChatService {
	messages: Readable<ChatMessage[]>;
	interviewerTyping: Readable<boolean>;
	send(text: string): Promise<void>;
}

export interface Services {
	conference: ConferenceService;
	participants: ParticipantsService;
	media: MediaService;
	chat: ChatService;
}
