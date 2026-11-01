import { useServices } from "../services/context";
import { useReadable } from "../hooks/useReadable";
import { Button, Card } from "../components";
import { Screen } from "../features/layout/Screen";
import { AppHeader } from "../features/AppHeader";
import { PageIntro } from "../features/layout/PageIntro";

export interface FinishedPageProps {
	onRestart: () => void;
}

export function FinishedPage(props: FinishedPageProps) {
	const { onRestart } = props;
	const state = useReadable(useServices().conference.state);

	return (
		<Screen header={<AppHeader />}>
			<div style={{ width: "100%", maxWidth: 560 }}>
				<Card>
					<div style={{ display: "grid", gap: 24 }}>
						<PageIntro
							title="Собеседование завершено"
							text={`Завершено тем: ${state.results?.length ?? 0}. Результаты предварительные и требуют проверки специалистом.`}
						/>
						{state.results?.map((r) => (
							<div key={r.cardId}>
								<strong>{r.cardId}</strong>
								<p>
									{r.score === null
										? "Требуется проверка"
										: `Предварительный балл: ${r.score}/10`}
									. Уточнений: {r.followups}
								</p>
							</div>
						))}
						{!!state.queue?.length && (
							<p>Не завершено тем: {state.queue.length}</p>
						)}
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
