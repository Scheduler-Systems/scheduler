import SwiftUI

struct GetNameView: View {
    @State private var name = ""
    @EnvironmentObject private var router: Router
    var onComplete: ((String) -> Void)?

    var body: some View {
        VStack(spacing: 24) {
            Text("What should we call you?")
                .font(.title2)
                .fontWeight(.semibold)

            TextField("Your name", text: $name)
                .textContentType(.name)
                .padding()
                .background(Color(red: 0.93, green: 0.93, blue: 0.97))
                .clipShape(RoundedRectangle(cornerRadius: 10))
                .padding(.horizontal)

            Button(action: {
                onComplete?(name)
                router.push(.chooseRole)
            }) {
                Text("Continue")
                    .fontWeight(.semibold)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(name.isEmpty ? Color.gray : Color.purple)
                    .foregroundColor(.white)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
            }
            .disabled(name.isEmpty)
            .padding(.horizontal)
        }
    }
}
