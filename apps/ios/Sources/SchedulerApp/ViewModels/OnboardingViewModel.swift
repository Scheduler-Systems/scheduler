import Foundation
import Combine

@MainActor
final class OnboardingViewModel: ObservableObject {
    @Published var currentPage = 0
    @Published var hasCompleted = false

    let pages = OnboardingContent.pages

    var onComplete: (() -> Void)?

    var isLastPage: Bool {
        currentPage == pages.count - 1
    }

    func nextPage() {
        guard currentPage < pages.count - 1 else { return }
        currentPage += 1
    }

    func previousPage() {
        guard currentPage > 0 else { return }
        currentPage -= 1
    }

    func goToPage(_ index: Int) {
        guard index >= 0, index < pages.count else { return }
        currentPage = index
    }

    func complete() {
        hasCompleted = true
        onComplete?()
    }
}
