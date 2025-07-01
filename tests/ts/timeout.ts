export async function executeSkill(env: any): Promise<[number, string, string | null]> {
    await new Promise(resolve => setTimeout(resolve, 10000)); // This will cause a timeout
    // This return should ideally not be reached if the timeout works correctly
    return [0.0, "Skill timed out.", null];
}
