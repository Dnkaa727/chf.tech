import { useEffect, useState, type ReactNode } from "react";
import { Button, Dialog, Notice } from "../components";
import { useConference } from "../hooks/useConference";
import { SELF_ID } from "../model/types";
import { ConferenceLayout } from "../features/layout/ConferenceLayout";
import { Stage } from "../features/stage/Stage";
import { StageContentView } from "../features/stage/renderers";
import { StateMessage } from "../features/status/StateMessage";
import { conferenceStates } from "../features/status/conferenceStates";
import { ControlBar } from "../features/ControlBar";
import { SidePanel } from "../features/SidePanel";
import { ParticipantsPanel } from "../features/ParticipantsPanel";
import { ChatPanel } from "../features/ChatPanel";

type PanelId = "participants" | "chat";

export interface ConferencePageProps {
	onLeave: () => void;
}

export function ConferencePage(props: ConferencePageProps) {
	const { onLeave } = props;

	const [panelId, setPanelId] = useState<PanelId | null>("chat");
	const c = useConference({ chatOpen: panelId === "chat" });

	useEffect(() => { if (c.state.status === "ended") onLeave(); }, [c.state.status, onLeave]);
 const [error, setError] = useState<string | null>(null);
 const [confirming, setConfirming] = useState(false);
	const toggle = (id: PanelId) =>
		setPanelId((cur) => (cur === id ? null : id));

	const panels: Record<PanelId, { title: string; render: () => ReactNode }> =
		{
			participants: {
				title: `Участники (${c.participants.length})`,
				render: () => (
					<ParticipantsPanel participants={c.participants} />
				),
			},
			chat: {
				title: "Чат",
				render: () => (
					<ChatPanel
						messages={c.messages}
						selfId={SELF_ID}
						interviewerTyping={c.interviewerTyping}
						onSend={c.actions.send}
					/>
				),
			},
		};

	const stateView = conferenceStates[c.state.status];

	const stage =
		c.state.status === "live" && c.speaker ? (
			<Stage
				name={c.speaker.name}
				role={c.speaker.roleLabel}
				speaking={c.speaker.speaking}
			>
				<StageContentView content={c.content} />
			</Stage>
		) : (
			stateView && (
				<StateMessage
					{...stateView}
					action={
						c.state.status === "ended" ? (
							<Button onClick={onLeave}>Продолжить</Button>
						) : undefined
					}
				/>
			)
		);

	const endCall = async () => {
		try { await c.actions.leave(); onLeave(); } catch (e) { setError(e instanceof Error ? e.message : "Не удалось завершить интервью"); }
	};

	const dev = c.devices;

	return (
		<ConferenceLayout
			stage={stage}
			overlay={
				<>
					{error && <p role="alert">{error}</p>}
                    {c.state.queue && <Notice text={`Осталось тем: ${c.state.queue.length}. Текущая: ${c.state.queue[0] ?? "—"}`} />}
                    {c.warning && <Notice tone="error" text={c.warning} />}
					{c.toast && <Notice text={c.toast} />}
				</>
			}
			panel={
				panelId && (
					<SidePanel
						title={panels[panelId].title}
						onClose={() => setPanelId(null)}
					>
						{panels[panelId].render()}
					</SidePanel>
				)
			}
			controls={
				<ControlBar
					left={[
						{
							id: "cam",
							icon: dev.camera === "on" ? "video" : "video-slash",
							label:
								dev.camera === "on"
									? "Выключить камеру"
									: "Включить камеру",
							iconVariant:
								dev.camera === "on" ? "neutral" : "alert",
							onClick: c.actions.toggleCamera,
						},
						{
							id: "mic",
							icon:
								dev.mic === "on"
									? "microphone"
									: "microphone-slash",
							label:
								dev.mic === "on"
									? "Выключить микрофон"
									: "Включить микрофон",
							iconVariant: dev.mic === "on" ? "neutral" : "alert",
							onClick: c.actions.toggleMic,
						},
					]}
					center={[
						{
							id: "people",
							icon: "user-group",
							label: "Участники",
							text: "Участники",
							buttonVariant:
								panelId === "participants"
									? "primary"
									: "tonal",
							onClick: () => toggle("participants"),
						},
						{
							id: "chat",
							icon: "comment",
							label: "Чат",
							text: "Чат",
							count: c.unread,
							buttonVariant:
								panelId === "chat" ? "primary" : "tonal",
							onClick: () => toggle("chat"),
						},
					]}
					right={[
						{
							id: "end",
							icon: "phone-slash",
							label: "Завершить",
							text: "Завершить",
							buttonVariant: "danger",
							onClick: () => setConfirming(true),
						},
					]}
				/>
			}
			dialog={
				confirming && (
					<Dialog
						title="Завершить собеседование?"
						text="Вы выйдете из конференции. Вернуться к беседе будет нельзя."
						confirmLabel="Завершить"
						cancelLabel="Остаться"
						danger
						onConfirm={() => endCall()}
						onCancel={() => setConfirming(false)}
					/>
				)
			}
		/>
	);
}
