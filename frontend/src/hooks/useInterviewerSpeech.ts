import { useEffect, useState, useSyncExternalStore } from "react";
import type { ChatMessage } from "../model/types";
import {
	BrowserAudioPlayer,
	loadInterviewAudio,
} from "../services/speech/genApiAudio";
import { InterviewerSpeech } from "../services/speech/interviewerSpeech";

export function useInterviewerSpeech(messages: ChatMessage[]) {
	const supported = typeof window !== "undefined" && "AudioContext" in window;
	const [controller] = useState(
		() =>
			new InterviewerSpeech(
				supported ? new BrowserAudioPlayer() : null,
				loadInterviewAudio,
			),
	);
	const state = useSyncExternalStore(
		controller.subscribe,
		controller.getSnapshot,
	);
	useEffect(() => controller.connect(), [controller]);
	useEffect(() => controller.update(messages), [controller, messages]);
	return {
		...state,
		supported,
		hasUnread: controller.hasUnread(messages),
		enable: controller.enable,
		stop: controller.stop,
		repeat: controller.repeat,
	};
}
