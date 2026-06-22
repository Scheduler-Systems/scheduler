import SwiftUI

// Legal documents: Privacy Policy + Terms & Conditions open the external Legal Center in
// the browser (parity with Flutter's policies page). Reached from Home.
struct PoliciesView: View {
    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            Link(destination: LegalDocuments.legalCenterURL) {
                Label("Privacy Policy", systemImage: "lock.shield")
            }
            Link(destination: LegalDocuments.legalCenterURL) {
                Label("Terms & Conditions", systemImage: "doc.text")
            }
            Text("Click on Privacy Policy or Terms & Conditions above to view the legal documents. They will open in your default browser.")
                .font(.footnote)
                .foregroundColor(.secondary)
            Spacer()
        }
        .padding()
        .navigationTitle("Policies")
    }
}
