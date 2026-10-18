import { useState } from "react";
import { Button, Card, Checkbox, TextField } from "../components";
import { Screen } from "../features/layout/Screen";
import { SplitLayout } from "../features/layout/SplitLayout";
import { PageIntro } from "../features/layout/PageIntro";
import { AppHeader } from "../features/AppHeader";
import { DeviceToggle } from "../features/DeviceToggle";
import { useMediaControls } from "../hooks/useMediaControls";

export interface PreparePageProps {
	onJoin: (name: string) => void;
}

export function PreparePage(props: PreparePageProps) {
	const { onJoin } = props;
	const { devices, toggleCamera, toggleMic } = useMediaControls();
	const [name, setName] = useState("");
	const [agree, setAgree] = useState(false);
	const ready = name.trim().length > 1 && agree;
	const denied = devices.camera === "denied" || devices.mic === "denied";

	const join = () => {
		if (ready) onJoin(name.trim());
	};

	return (
		<Screen header={<AppHeader />}>
			<SplitLayout
				left={
					<PageIntro
						title="Подготовьтесь к собеседованию"
						text="Проверьте камеру и микрофон перед входом. Собеседование проведут ИИ-интервьюеры."
					/>
				}
				right={
					<Card>
						<div style={{ display: "grid", gap: 24 }}>
							<TextField
								id="name"
								value={name}
								onChange={setName}
								placeholder="Имя и фамилия"
								hint="Так вас увидят участники"
								autoFocus
								onSubmit={join}
							/>
							<div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
								<DeviceToggle
									kind="camera"
									state={devices.camera}
									onClick={toggleCamera}
								/>
								<DeviceToggle
									kind="mic"
									state={devices.mic}
									onClick={toggleMic}
								/>
							</div>
							{denied && (
								<TextField
									id="denied-note"
									value=""
									onChange={() => undefined}
									error="Нет доступа к устройству. Разрешите его в настройках браузера или войдите без него."
								/>
							)}
							<Checkbox checked={agree} onChange={setAgree}>
								Я даю своё{" "}
								<a href="#">согласие на обработку персональных данных</a>
							</Checkbox>
							<Button
								size="l"
								fullWidth
								iconRight="arrow-right"
								disabled={!ready}
								onClick={join}
							>
								Войти в конференцию
							</Button>
						</div>
					</Card>
				}
			/>
		</Screen>
	);
}
