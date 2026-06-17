import SwiftUI

struct OnboardingView: View {
    @StateObject private var vm = OnboardingViewModel()

    var body: some View {
        VStack {
            TabView(selection: $vm.currentPage) {
                ForEach(Array(vm.pages.enumerated()), id: \.element.id) { i, page in
                    onboardingPage(page).tag(i)
                }
            }
            #if os(iOS)
            .tabViewStyle(.page(indexDisplayMode: .always))
            #endif

            Button(action: { vm.complete() }) {
                Text("Start Now")
                    .fontWeight(.semibold)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(Color.purple)
                    .foregroundColor(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
            }
            .padding(.horizontal, 20)
            .padding(.bottom, 20)
        }
    }

    private func onboardingPage(_ content: OnboardingContent) -> some View {
        VStack(spacing: 24) {
            Spacer()

            Image(systemName: icon(for: content.id))
                .resizable()
                .scaledToFit()
                .frame(width: 120, height: 120)
                .foregroundColor(.purple)

            Text(content.title)
                .font(.title)
                .fontWeight(.bold)
                .multilineTextAlignment(.center)

            Text(content.description)
                .font(.body)
                .multilineTextAlignment(.center)
                .foregroundColor(.secondary)
                .padding(.horizontal, 32)

            Spacer()
        }
    }

    private func icon(for id: String) -> String {
        switch id {
        case "stay_connected": return "person.2.wave.2"
        case "customizable_approach": return "slider.horizontal.3"
        case "algorithmic_calculation": return "brain.head.profile"
        default: return "star"
        }
    }
}
