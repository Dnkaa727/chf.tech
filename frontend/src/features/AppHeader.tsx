import { Button } from "../components";

export function AppHeader() {
	return (
		<header className="app-header">
			<span className="app-header__logo">Логотип</span>
			<div className="app-header__actions">
				<Button variant="tonal">Помощь</Button>
				<a className="app-header__link" href="#">
					О компании
				</a>
			</div>
		</header>
	);
}
