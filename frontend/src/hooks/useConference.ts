import { useEffect, useMemo, useRef, useState } from "react";
import { useServices } from "../services/context";
import { useReadable } from "./useReadable";
import { SELF_ID, type StageContent } from "../model/types";

export interface UseConferenceProps {
	chatOpen: boolean;
}

export function useConference(props: UseConferenceProps) {
	const { chatOpen } = props;
	const s = useServices();
	const state = useReadable(s.conference.state);
	const notice = useReadable(s.conference.events);
	const raw = useReadable(s.participants.list);
	const contents = useReadable(s.participants.content);
	const devices = useReadable(s.media.devices);
	const stream = useReadable(s.media.localStream);
	const messages = useReadable(s.chat.messages);
	const interviewerTyping = useReadable(s.chat.interviewerTyping);

	const participants = useMemo(
		() =>
			raw.map((p) =>
				p.id === SELF_ID
					? {
							...p,
							cameraOn: devices.camera === "on",
							micOn: devices.mic === "on",
						}
					: p,
			),
		[raw, devices],
	);

	const lastSpeaker = useRef<string | undefined>(undefined);
	const current = participants.find((p) => p.speaking);

	if (current) lastSpeaker.current = current.id;

	const speaker =
		participants.find((p) => p.id === lastSpeaker.current) ??
		participants.find((p) => p.id !== SELF_ID) ??
		participants[0];

	let content: StageContent = (speaker && contents[speaker.id]) || {
		type: "avatar",
	};

	if (speaker?.id === SELF_ID && devices.camera === "on")
		content = { type: "video", stream };

	const [toast, setToast] = useState<string | null>(null);

	useEffect(() => {
		if (!notice) return;
		setToast(notice.text);
		const t = window.setTimeout(() => setToast(null), 3500);
		return () => window.clearTimeout(t);
	}, [notice]);

	const [seen, setSeen] = useState(0);

	useEffect(() => {
		if (chatOpen) setSeen(messages.length);
	}, [chatOpen, messages.length]);

	const unread = chatOpen ? 0 : Math.max(0, messages.length - seen);

	const warning =
		devices.camera === "denied"
			? "Нет доступа к камере. Разрешите доступ в настройках браузера."
			: devices.mic === "denied"
				? "Нет доступа к микрофону. Разрешите доступ в настройках браузера."
				: null;

	return {
		state,
		participants,
		speaker,
		content,
		messages,
		interviewerTyping,
		unread,
		toast,
		warning,
		devices,
		actions: {
			toggleCamera: () => void s.media.setCamera(devices.camera !== "on"),
			toggleMic: () => void s.media.setMic(devices.mic !== "on"),
			send: (text: string) => s.chat.send(text),
			leave: () => s.conference.leave(),
		},
	};
}
