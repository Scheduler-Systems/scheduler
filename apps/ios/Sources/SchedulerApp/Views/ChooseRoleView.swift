import SwiftUI

struct ChooseRoleView: View {
    @StateObject private var vm = ChooseRoleViewModel()
    @EnvironmentObject private var router: Router

    var body: some View {
        VStack(spacing: 24) {
            Spacer()

            Text("Choose Your Role")
                .font(.title)
                .fontWeight(.bold)

            Text("Choose your role, so that we personalize your experience")
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal)

            Image(systemName: "person.2")
                .resizable()
                .scaledToFit()
                .frame(height: 180)
                .foregroundColor(.purple.opacity(0.3))

            Spacer()

            VStack(spacing: 16) {
                Button(action: {
                    vm.selectManager()
                    router.push(.home)
                }) {
                    Text("Log In as Manager")
                        .fontWeight(.semibold)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.purple)
                        .foregroundColor(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }

                Button(action: {
                    vm.selectEmployee()
                    router.push(.home)
                }) {
                    Text("Log In as Employee")
                        .fontWeight(.semibold)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.pink)
                        .foregroundColor(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }
            }
            .padding(.horizontal, 16)

            Spacer()
        }
    }
}
