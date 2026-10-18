import { Button, Card } from "../components";
import { Screen } from "../features/layout/Screen";
import { AppHeader } from "../features/AppHeader";
import { PageIntro } from "../features/layout/PageIntro";

export interface FinishedPageProps {
	onRestart: () => void;
}

export function FinishedPage(props: FinishedPageProps) {
	const { onRestart } = props;

	return (
		<Screen header={<AppHeader />}>
			<div style={{ width: "100%", maxWidth: 560 }}>
				<Card>
					<div style={{ display: "grid", gap: 24 }}>
						<PageIntro
							title="Собеседование завершено"
							text="Спасибо за уделённое время. Мы свяжемся с вами в ближайшее время."
						/>
						<Button
							size="l"
							fullWidth
							iconRight="arrow-right"
							onClick={onRestart}
						>
							Вернуться в начало
						</Button>
					</div>
				</Card>
			</div>
		</Screen>
	);
}
