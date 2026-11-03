import { App, Plugin, PluginSettingTab, Setting, TFile } from "obsidian";
import { HomeView } from "./home";

const HOME = "StatPearls/Hubs/Home (hub).md";

interface Settings {
  openHomeOnStart: boolean;
}

export default class StatPearlsPlugin extends Plugin {
  settings: Settings = { openHomeOnStart: true };

  async onload() {
    this.settings = { ...this.settings, ...(await this.loadData()) };
    this.registerMarkdownCodeBlockProcessor("statpearls-home", (source, el, ctx) => {
      let data;
      try {
        data = JSON.parse(source);
      } catch {
        el.createDiv({ text: "StatPearls Home: the data block is not valid JSON; rebuild the vault." });
        return;
      }
      ctx.addChild(new HomeView(this.app, el, data));
    });
    this.addCommand({ id: "open-home", name: "Open home", callback: () => this.openHome() });
    this.addRibbonIcon("search", "StatPearls home", () => this.openHome());
    this.addSettingTab(new StatPearlsSettings(this.app, this));
    this.app.workspace.onLayoutReady(() => {
      if (this.settings.openHomeOnStart) this.openHome();
    });
  }

  async openHome() {
    const file = this.app.vault.getAbstractFileByPath(HOME);
    if (file instanceof TFile) await this.app.workspace.getLeaf(false).openFile(file, { state: { mode: "preview" } });
  }
}

class StatPearlsSettings extends PluginSettingTab {
  constructor(app: App, private plugin: StatPearlsPlugin) {
    super(app, plugin);
  }

  display() {
    this.containerEl.empty();
    new Setting(this.containerEl)
      .setName("Open Home on start")
      .setDesc("Open StatPearls Home in reading view when the vault opens.")
      .addToggle((t) =>
        t.setValue(this.plugin.settings.openHomeOnStart).onChange(async (v) => {
          this.plugin.settings.openHomeOnStart = v;
          await this.plugin.saveData(this.plugin.settings);
        }),
      );
  }
}
