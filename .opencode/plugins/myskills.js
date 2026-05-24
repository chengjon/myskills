import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const pluginRoot = join(__dirname, "..", "..");
const skillsDir = join(pluginRoot, "skills");

export const MySkillsPlugin = async ({ client, directory }) => {
  return {
    config: async (config) => {
      config.skills.paths.push(skillsDir);
    },
  };
};
