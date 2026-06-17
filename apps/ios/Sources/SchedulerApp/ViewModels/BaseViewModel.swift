import Foundation
import Combine

@MainActor
class BaseViewModel: ObservableObject {
    @Published var isLoading = false
    @Published var error: Error?
    
    var cancellables = Set<AnyCancellable>()
    
    func handle(_ error: Error) {
        self.error = error
    }
    
    func clearError() {
        self.error = nil
    }
}
