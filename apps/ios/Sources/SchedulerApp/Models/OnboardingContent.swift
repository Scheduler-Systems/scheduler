import Foundation

struct OnboardingContent: Identifiable {
    let id: String
    let title: String
    let description: String
    let lightImagePath: String
    let darkImagePath: String

    static let pages: [OnboardingContent] = [
        OnboardingContent(
            id: "stay_connected",
            title: "Stay Connected",
            description: "Keep your team in sync with real-time schedule updates, shift changes, and availability management.",
            lightImagePath: "onboarding_connected_light",
            darkImagePath: "onboarding_connected_dark"
        ),
        OnboardingContent(
            id: "customizable_approach",
            title: "Customizable Approach",
            description: "Tailor schedules to fit your team's unique needs with flexible shift patterns and role-based assignments.",
            lightImagePath: "onboarding_customize_light",
            darkImagePath: "onboarding_customize_dark"
        ),
        OnboardingContent(
            id: "algorithmic_calculation",
            title: "Smart Scheduling",
            description: "Let our algorithm handle complex scheduling constraints so you can focus on what matters most.",
            lightImagePath: "onboarding_smart_light",
            darkImagePath: "onboarding_smart_dark"
        ),
    ]
}
